import { Localized, useLocalization } from "@fluent/react";
import type { NextPage } from "next";
import styles from "./profile.module.scss";
import BottomBannerIllustration from "../../../../static/images/woman-couch-left.svg";
import { Layout } from "../../components/layout/Layout";
import { useProfiles } from "../../hooks/api/profile";
import {
  AliasData,
  getAllAliases,
  isRandomAlias,
  useAliases,
} from "../../hooks/api/aliases";
import { useUsers } from "../../hooks/api/user";
import { AliasList } from "../../components/dashboard/AliasList";
import { SubdomainPicker } from "../../components/dashboard/SubdomainPicker";
import { toast } from "react-toastify";
import { ProfileBanners } from "../../components/dashboard/ProfileBanners";
import { LinkButton } from "../../components/Button";
import { usePremiumCountries } from "../../hooks/api/premiumCountries";
import {
  getPremiumSubscribeLink,
  isPremiumAvailableInCountry,
} from "../../functions/getPlan";
import { useGaPing } from "../../hooks/gaPing";
import { trackPurchaseStart } from "../../functions/trackPurchase";

const Profile: NextPage = () => {
  const profileData = useProfiles();
  const userData = useUsers();
  const { randomAliasData, customAliasData } = useAliases();
  const premiumCountriesData = usePremiumCountries();
  const { l10n } = useLocalization();
  const bottomBannerSubscriptionLinkRef = useGaPing({
    category: "Purchase Button",
    label: "profile-bottom-promo",
  });

  const profile = profileData.data?.[0];
  const user = userData.data?.[0];
  if (!profile || !user || !randomAliasData.data || !customAliasData.data) {
    // TODO: Show a loading spinner?
    // TODO: Redirect the user to the login page if they're not logged in?
    return null;
  }

  const createAlias = () => {
    randomAliasData.create();
  };

  const updateAlias = (alias: AliasData, updatedFields: Partial<AliasData>) => {
    if (isRandomAlias(alias)) {
      randomAliasData.update({ ...updatedFields, id: alias.id });
    } else {
      customAliasData.update({ ...updatedFields, id: alias.id });
    }
  };

  const deleteAlias = (alias: AliasData) => {
    if (isRandomAlias(alias)) {
      randomAliasData.delete(alias.id);
    } else {
      customAliasData.delete(alias.id);
    }
  };

  const allAliases = getAllAliases(randomAliasData.data, customAliasData.data);

  const totalBlockedEmails = allAliases.reduce(
    (count, alias) => count + alias.num_blocked,
    0
  );
  const totalForwardedEmails = allAliases.reduce(
    (count, alias) => count + alias.num_forwarded,
    0
  );

  const setCustomSubdomain = async (customSubdomain: string) => {
    const response = await profileData.update(profile.id, {
      subdomain: customSubdomain,
    });
    if (response.ok) {
      toast(
        l10n.getString("modal-domain-register-success", {
          subdomain: customSubdomain,
        }),
        { type: "success" }
      );
    }
  };

  // Non-Premium users have only five aliases, making the stats less insightful,
  // so only show them for Premium users:
  const stats = profile.has_premium ? (
    <header className={styles.header}>
      <div className={styles.headerWrapper}>
        <Localized
          id="profile-label-welcome-html"
          vars={{
            email: user.email,
          }}
          elems={{
            span: <span className={styles.lead} />,
          }}
        >
          <span className={styles.greeting} />
        </Localized>
        <div className={styles.accountStats}>
          <span className={styles.stat}>
            <span className={styles.label}>
              {l10n.getString("profile-stat-label-aliases-used")}
            </span>
            <span className={styles.value}>{allAliases.length}</span>
          </span>
          <span className={styles.stat}>
            <span className={styles.label}>
              {l10n.getString("profile-stat-label-blocked")}
            </span>
            <span className={styles.value}>{totalBlockedEmails}</span>
          </span>
          <span className={styles.stat}>
            <span className={styles.label}>
              {l10n.getString("profile-stat-label-forwarded")}
            </span>
            <span className={styles.value}>{totalForwardedEmails}</span>
          </span>
        </div>
      </div>
    </header>
  ) : (
    <Localized
      id="profile-label-welcome-html"
      vars={{ email: user.email }}
      elems={{ span: <span /> }}
    >
      <p className={styles.noPremiumHeader} />
    </Localized>
  );

  const bottomBanner =
    profile.has_premium ||
    !isPremiumAvailableInCountry(premiumCountriesData.data) ? null : (
      <div className={styles.bottomBanner}>
        <div className={styles.bottomBannerWrapper}>
          <div className={styles.bottomBannerContent}>
            <Localized
              id="banner-pack-upgrade-headline-html"
              elems={{ strong: <strong /> }}
            >
              <h3 />
            </Localized>
            <p>{l10n.getString("banner-pack-upgrade-copy")}</p>
            <LinkButton
              href={getPremiumSubscribeLink(premiumCountriesData.data)}
              ref={bottomBannerSubscriptionLinkRef}
              onClick={() =>
                trackPurchaseStart({ label: "profile-bottom-promo" })
              }
            >
              {l10n.getString("banner-pack-upgrade-cta")}
            </LinkButton>
          </div>
          <img src={BottomBannerIllustration.src} alt="" />
        </div>
      </div>
    );

  return (
    <>
      <Layout>
        {stats}
        <div className={styles.bannersWrapper}>
          <ProfileBanners profile={profile} />
        </div>
        <main className={styles.mainWrapper}>
          <SubdomainPicker profile={profile} onCreate={setCustomSubdomain} />
          <AliasList
            aliases={allAliases}
            onCreate={createAlias}
            onUpdate={updateAlias}
            onDelete={deleteAlias}
            profile={profile}
            user={user}
            premiumCountries={premiumCountriesData.data}
          />
          <p className={styles.sizeInformation}>
            {l10n.getString("profile-supports-email-forwarding", {
              size: process.env.NEXT_PUBLIC_EMAIL_SIZE_LIMIT_NUMBER!,
              unit: process.env.NEXT_PUBLIC_EMAIL_SIZE_LIMIT_UNIT!,
            })}
          </p>
        </main>
        {bottomBanner}
      </Layout>
    </>
  );
};

export default Profile;